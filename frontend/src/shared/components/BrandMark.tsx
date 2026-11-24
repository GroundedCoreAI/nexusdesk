import type {ReactNode} from 'react';
import './brand-mark.css';

/** NexusDesk's approved geometric N symbol, exported as a transparent asset. */
export function BrandGlyph({className}:{className?:string}) {
  return (
    <img
      className={['brand-glyph',className].filter(Boolean).join(' ')}
      src="/images/nexusdesk-mark.png"
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}

/** Shared NexusDesk brand lockup for the login screen and console sidebar. */
export function BrandMark({
  size='md',
  subtitle,
  showGlyph=true,
  showDot=false,
  className,
}:{
  size?:'md'|'lg';
  subtitle?:ReactNode;
  showGlyph?:boolean;
  showDot?:boolean;
  className?:string;
}) {
  return (
    <span className={['brand-mark','brand-mark--'+size,className].filter(Boolean).join(' ')}>
      {showGlyph&&<BrandGlyph/>}
      <span className="brand-mark__body">
        <span className="brand-mark__word">
          <span className="brand-mark__name">NexusDesk</span>
          {showDot&&<i className="brand-mark__dot" aria-hidden="true"/>}
        </span>
        {subtitle&&<small className="brand-mark__subtitle">{subtitle}</small>}
      </span>
    </span>
  );
}
